import numpy as np
import numba
import defaultParameters as dp

def timeIntegration(params):

    """    
    TIMEINTEGRATION : Simulate a network of aLN modules
      
    Return:
      rates_exc:  N*L array   : containing the exc. neuron rates in kHz time series of the N nodes
      rates_inh:  N*L array   : containing the inh. neuron rates in kHz time series of the N nodes
      t:          L array     : the time value at which the time series are evaluated
      mufe:       N vector    : final value of mufe for each node
      mufi:       N vector    : final value of mufi for each node
      IA:         N vector    : final value of IA   for each node
      seem :      N vector    : final value of seem  for each node
      seim :      N vector    : final value of seim  for each node
      siem :      N vector    : final value of siem  for each node
      siim :      N vector    : final value of siim  for each node
      seev :      N vector    : final value of seev  for each node
      seiv :      N vector    : final value of seiv  for each node
      siev :      N vector    : final value of siev  for each node
      siiv :      N vector    : final value of siiv  for each node
    """     
    
    dt = params['dt']               # Time step for the Euler intergration (ms)
    duration = params['duration']   # imulation duration (ms)

    RNGseed = params['seed']        # seed for RNG
    
    warn = params['warn']       # Display a warning if out og precalc limits in interpolation,
                                # set to 0 for faster computation
    
    # ------------------------------------------------------------------------
    # global coupling parameters
    
    # Connectivity matric
    Cmat = params['Cmat'] # Interareal relative coupling strengths (values between 0 and 1), Cmat(i,j) connnection from jth to ith
    N = len(Cmat)         # Number of areas    
     
    # Interareal connection delay
         
    lengthMat = params['lengthMat']
    
    signalV = params['signalV']
   
    if N == 1:
        Dmat = np.ones((N,N))*params['de']
    else:
        Dmat = dp.computeDelayMatrix(lengthMat,signalV) # Interareal connection delays, Dmat(i,j) Connnection from jth node to ith (ms)
        Dmat[np.eye(len(Dmat))==1] = np.ones(len(Dmat))*params['de']
    
        
    Dmat_ndt = np.around(Dmat/dt).astype(int)  # delay matrix in multiples of dt
    params['Dmat_ndt'] = Dmat_ndt
    #print(Dmat_ndt)
    #print(np.max(Dmat_ndt), np.min(Dmat_ndt))
    c_gl     = params['c_gl']       # global coupling strength between areas(unitless)
    Ke_gl    = params['Ke_gl']     # number of incoming E connections (to E population) from each area

    # ------------------------------------------------------------------------
    
    # local network (area) parameters [identical for all areas for now]
    
    ### model parameters
    dosc_version = params['dosc_version']  # (Use dynamic oscillations?) if 0: exponential version (fewer dimensions, faster)
    filter_sigma = params['filter_sigma']
    distr_delay  = params['distr_delay']
    fast_interp  = params['fast_interp']    
    global_delay = params['global_delay']
    
    # external input parameters:
    tau_ou       = params['tau_ou']     # Parameter of the Ornstein-Uhlenbeck process for the external input(ms)
    sigma_ou     = params['sigma_ou'] # Parameter of the Ornstein-Uhlenbeck (OU) process for the external input ( mV/ms/sqrt(ms) )
    mue_ext_mean = params['mue_ext_mean']  # Mean external excitatory input (OU process) (mV/ms)
    mui_ext_mean = params['mui_ext_mean']  # Mean external inhibitory input (OU process) (mV/ms)
    sigmae_ext   = params['sigmae_ext']  # External exc input standard deviation ( mV/sqrt(ms) )
    sigmai_ext   = params['sigmai_ext']  # External inh input standard deviation ( mV/sqrt(ms) )

 

    # recurrent coupling parameters
    Ke = params['Ke']  # Recurrent Exc coupling. "EE = IE" assumed for act_dep_coupling in current implementation
    Ki = params['Ki']  # Recurrent Exc coupling. "EI = II" assumed for act_dep_coupling in current implementation

    # Recurrent connection delays
    de = params['de']  # Local constant delay "EE = IE" (ms)
    di = params['di']  # Local constant delay "EI = II" (ms)


    tau_se = params['tau_se']    # Synaptic decay time constant for exc. connections "EE = IE" (ms)
    tau_si = params['tau_si']    # Synaptic decay time constant for inh. connections  "EI = II" (ms)
    tau_de = params['tau_de']
    tau_di = params['tau_di']
    
    cee = params['cee']            # strength of exc. connection
                                   #  -> determines ePSP magnitude in state-dependent way (in the original model)    
    cie = params['cie']            # strength of inh. connection
                                   #   -> determines iPSP magnitude in state-dependent way (in the original model)
    cei = params['cei']
    cii = params['cii']

    # Recurrent connections coupling strength
    Jee_max = params['Jee_max']   # ( mV/ms )
    Jei_max = params['Jei_max']   # ( mV/ms )
    Jie_max = params['Jie_max']   # ( mV/ms )
    Jii_max = params['Jii_max']   # ( mV/ms )
    
    # rescales c's here: multiplication with tau_se makes 
    # the increase of s subject to a single input spike invariant to tau_se
    # division by J ensures that mu = J*s will result in a PSP of exactly c
    # for a single spike!

    cee = cee*tau_se/Jee_max  #ms
    cie = cie*tau_se/Jie_max  #ms
    cei = cei*tau_si/abs(Jei_max)  #ms
    cii = cii*tau_si/abs(Jii_max)  #ms
    c_gl = c_gl*tau_se/Jee_max  #ms
    
    # neuron model parameters
    a      = params['a']         # Adaptation coupling term ( nS )
    b      = params['b']         # Spike triggered adaptation ( pA )
    EA     = params['EA']       # Adaptation reversal potential ( mV )
    tauA   = params['tauA']   # Adaptation time constant ( ms )
    # if params below are changed, preprocessing required
    C      = params['C']         # membrane capacitance ( pF )
    gL     = params['gL']       # Membrane conductance ( nS )
    EL     = params['EL']       # Leak reversal potential ( mV )
    DeltaT = params['DeltaT'] # Slope factor ( EIF neuron ) ( mV )   
    VT     = params['VT']       # Effective threshold (in exp term of the aEIF model)(mV)
    Vr     = params['Vr']       # Membrane potential reset value (mV)
    Vs     = params['Vs']       # Cutoff or spike voltage value, determines the time of spike (mV)
    Tref   = params['Tref']   # Refractory time (ms)
    taum   = C/gL             # membrane time constant

    # ------------------------------------------------------------------------
    # ------------------------------------------------------------------------

    mufe      = params['mufe_init'].copy()    # Filtered mean input (mu) for exc. population
    mufi      = params['mufi_init'].copy()    # Filtered mean input (mu) for inh. population
    mufe_dosc = params['mufe_init'].copy() + np.zeros(N)*(1j) # (if dosc_version: complex variable) (mV/ms)
    mufi_dosc = params['mufi_init'].copy() + np.zeros(N)*(1j) # (if dosc_version: complex variable) (mV/ms)   
    IA        = params['IA_init'].copy()    # Adaptation current (pA)
    seem      = params['seem_init'].copy()   # Mean exc synaptic input
    seim      = params['seim_init'].copy()
    seev      = params['seev_init'].copy()   # Exc synaptic input variance
    seiv      = params['seiv_init'].copy()
    siim      = params['siim_init'].copy()   # Mean inh synaptic input
    siem      = params['siem_init'].copy()
    siiv      = params['siiv_init'].copy()   # Inh synaptic input variance
    siev      = params['siev_init'].copy()


    # Lookup tables for the transfer functions
    precalc_r, precalc_V, precalc_tau_mu, precalc_tau_sigma = params['precalc_r'], params['precalc_V'], params['precalc_tau_mu'], params['precalc_tau_sigma'] 
    
    # parameter for the lookup tables
    dI         = params['dI']
    ds         = params['ds']
    sigmarange = params['sigmarange']
    Irange     = params['Irange']  
  

    # Initialization
    t = np.arange(0,duration,dt)     # Time variable (ms)
    
    sqrt_dt = np.sqrt(dt)
    
    ndt_de = np.around(de/dt).astype(int)
    ndt_di = np.around(di/dt).astype(int)

    if not global_delay: # if no network delays, fill delay matrix with zeroes
        Dmat_ndt = np.zeros((N,N)) # ATTENTION: this will also get rid of the INTRA-network delays (which is modelled as a E-E delay)        
    max_global_delay = np.max(Dmat_ndt)
    startind = int(np.max([max_global_delay, ndt_de, ndt_di])+1)
    #print("Startind: {}, len(t): {}, simulation steps: {}".format(startind, len(t), len(range(startind-1,len(t)))))

    mue_ext = mue_ext_mean*np.ones((N,))  # Mean external exc input (mV/ms)
    mui_ext = mui_ext_mean*np.ones((N,))  # Mean external inh inout (mV/ms)
    # Set the initial firing rates.
    if np.shape(params['rates_exc_init'])[1] == 1:
        # If the initial firing rate is a 1D array, we use a fixed firing for a time "max_delay" before the simulation
        rates_exc = np.dot(params['rates_exc_init'], np.ones((1,len(t))))  #kHz
        rates_inh = np.dot(params['rates_inh_init'], np.ones((1,len(t))))  #kHz
    else:
        # Reuse the firing rates computed in a precedent simulation
        rates_exc = np.zeros((N,len(t)))
        rates_inh = np.zeros((N,len(t)))
        rates_exc[:,0:startind-1] = params['rates_exc_init'][:,-startind:]
        rates_inh[:,0:startind-1] = params['rates_inh_init'][:,-startind:]
    if distr_delay:
        rd_exc = 0.01*np.ones((N,N))
        rd_inh = 0.01*np.ones(N)
        
        for l in range(N):
            Dmat_ndt[l,l] = 0.0 # if distributed, this will calculated in the r_d ODE (Eq. 4.43)
    else:
        rd_exc = np.zeros((N,N))  #kHz  rd_exc(i,j): Connection from jth node to ith     
        rd_inh = np.zeros(N)
        
        for l in range(N):
            Dmat_ndt[l,l] = ndt_de  # if no distributed, this is a fixed value (E-E coupling)
   
    # Save the noise in the rates array to save memory
    if RNGseed:
        np.random.seed(RNGseed)
    rates_exc[:,startind:] = np.random.standard_normal( ( N, len ( range(startind,len(t) ) ) ) ) 
    rates_inh[:,startind:] = np.random.standard_normal( ( N, len ( range(startind,len(t) ) ) ) ) 

    noise_exc = np.zeros((N,))
    noise_inh = np.zeros((N,))
    
    zeros4 = np.zeros((4,))    
    
    # ------------------------------------------------------------------------
    # PREPARE OBJECTS FOR RETURNING VALUES

    r_ext_chunk = np.zeros(rates_exc.shape)    
    mue_ext_chunk = np.zeros(rates_exc.shape) 
    mui_ext_chunk = np.zeros(rates_exc.shape)
    sigmae_chunk = np.zeros(rates_exc.shape)
    sigmai_chunk = np.zeros(rates_exc.shape) 
    seem_chunk = np.zeros(rates_exc.shape)
    siim_chunk = np.zeros(rates_exc.shape)
    seim_chunk = np.zeros(rates_exc.shape)
    siem_chunk = np.zeros(rates_exc.shape)
    seev_chunk = np.zeros(rates_exc.shape)
    siiv_chunk = np.zeros(rates_exc.shape)
    seiv_chunk = np.zeros(rates_exc.shape)
    siev_chunk = np.zeros(rates_exc.shape) 

    mufe_chunk = np.zeros(rates_exc.shape)
    mufi_chunk = np.zeros(rates_exc.shape) 
    IA_chunk = np.zeros(rates_exc.shape) 

    tau_exc_chunk = np.zeros(rates_exc.shape)
    tau_inh_chunk = np.zeros(rates_exc.shape)
    
    # tile external inputs to appropriate shape

    ext_exc_current = adjust_shape(params['ext_exc_current'], rates_exc)
    ext_inh_current = adjust_shape(params['ext_inh_current'], rates_exc)    
    ext_exc_rate = adjust_shape(params['ext_exc_rate'], rates_exc)
    ext_inh_rate = adjust_shape(params['ext_inh_rate'], rates_exc)

    # ------------------------------------------------------------------------

    return timeIntegration_njit_elementwise(dt, duration,
                    warn, dosc_version,
                    distr_delay, filter_sigma, fast_interp,
                    Cmat, Dmat,
                    c_gl, Ke_gl,
                    tau_ou, sigma_ou,
                    mue_ext_mean, mui_ext_mean,
                    sigmae_ext, sigmai_ext,
                    Ke, Ki,
                    de, di,
                    tau_se, tau_si,
                    tau_de, tau_di,
                    cee, cie, cii, cei,
                    Jee_max, Jei_max, Jie_max, Jii_max,
                    a, b,
                    EA, tauA,
                    C, gL, EL, DeltaT, VT, Vr, Vs, Tref, taum,
                    mufe, mufi, mufe_dosc, mufi_dosc,
                    IA,
                    seem, seim, seev, seiv, siim, siem, siiv, siev,
                    precalc_r, precalc_V, precalc_tau_mu, precalc_tau_sigma,
                    dI, ds,
                    sigmarange, Irange,
                    N, Dmat_ndt,
                    t, rates_exc, rates_inh,
                    rd_exc, rd_inh,
                    sqrt_dt, startind,
                    ndt_de, ndt_di,
                    max_global_delay,
                    mue_ext, mui_ext,
                    r_ext_chunk, 
                    mue_ext_chunk, mui_ext_chunk,
                    sigmae_chunk, sigmai_chunk,
                    mufe_chunk, mufi_chunk, 
                    seem_chunk, siim_chunk,
                    seim_chunk, siem_chunk,
                    seev_chunk, siiv_chunk,
                    seiv_chunk, siev_chunk,                     
                    IA_chunk,
                    tau_exc_chunk, tau_inh_chunk,
                    ext_exc_rate, ext_inh_rate,
                    ext_exc_current, ext_inh_current,
                    noise_exc, noise_inh, zeros4)




@numba.njit(locals = {'idxX': numba.int64, 'idxY':numba.int64, 'idx1':numba.int64, 'idy1':numba.int64})
def timeIntegration_njit_elementwise(dt, duration,
                    warn, dosc_version,
                    distr_delay, filter_sigma, fast_interp,
                    Cmat, Dmat,
                    c_gl, Ke_gl,
                    tau_ou, sigma_ou,
                    mue_ext_mean, mui_ext_mean,
                    sigmae_ext, sigmai_ext,
                    Ke, Ki,
                    de, di,
                    tau_se, tau_si,
                    tau_de, tau_di,
                    cee, cie, cii, cei,
                    Jee_max, Jei_max, Jie_max, Jii_max,
                    a, b,
                    EA, tauA,
                    C, gL, EL, DeltaT, VT, Vr, Vs, Tref, taum,
                    mufe, mufi, mufe_dosc, mufi_dosc,
                    IA,
                    seem, seim, seev, seiv, siim, siem, siiv, siev,
                    precalc_r, precalc_V, precalc_tau_mu, precalc_tau_sigma,
                    dI, ds,
                    sigmarange, Irange,
                    N, Dmat_ndt,
                    t, rates_exc, rates_inh,
                    rd_exc, rd_inh,
                    sqrt_dt, startind,
                    ndt_de, ndt_di,
                    max_global_delay,
                    mue_ext, mui_ext,
                    r_ext_chunk, 
                    mue_ext_chunk, mui_ext_chunk,
                    sigmae_chunk, sigmai_chunk,
                    mufe_chunk, mufi_chunk, 
                    seem_chunk, siim_chunk,
                    seim_chunk, siem_chunk,
                    seev_chunk, siiv_chunk,
                    seiv_chunk, siev_chunk,                    
                    IA_chunk,
                    tau_exc_chunk, tau_inh_chunk,
                    ext_exc_rate, ext_inh_rate,
                    ext_exc_current, ext_inh_current,
                    noise_exc, noise_inh, zeros4):    
     

    # squared Jee_max 
    sq_Jee_max = Jee_max**2
    sq_Jei_max = Jei_max**2
    sq_Jie_max = Jie_max**2
    sq_Jii_max = Jii_max**2
    
    
    # initialize so we don't get an error when returning
    rd_exc_rhs = 0.0
    rd_inh_rhs = 0.0                
    sigmae_f_rhs = 0.0
    sigmai_f_rhs = 0.0

    if filter_sigma:
        sigmae_f = sigmae_ext
        sigmai_f = sigmai_ext
        

    ### integrate ODE system:
    for i in range(startind,len(t)):

        # loop through all the nodes
        for no in range(N):        
        
        
            # To save memory, noise is saved in the rates array
            noise_exc[no] = rates_exc[no,i]
            noise_inh[no] = rates_inh[no,i]
        
            # Get the input from one node into another from the rates at time t - connection_delay
            # remark: assume Kie == Kee and Kei == Kii
        
            if not distr_delay:
                # interareal coupling
                for l in range(N):
                    rd_exc[l,no] = rates_exc[no,i-Dmat_ndt[l,no]-1] # rd_exc(i,j) delayed input rate from population j to population i  
                rd_inh[no] = rates_inh[no,i-ndt_di-1]   # Warning: this is a vector and not a matrix as rd_exc
        
            mue = Jee_max*seem[no] + Jei_max*seim[no] + mue_ext[no] + ext_exc_current[no,i]
            mui = Jie_max*siem[no] + Jii_max*siim[no] + mui_ext[no] + ext_inh_current[no,i]
                        
            # compute row sum of Cmat*rd_exc and Cmat**2*rd_exc
            rowsum = 0
            rowsumsq = 0
            for col in range(N):
                rowsum = rowsum + Cmat[no,col]*rd_exc[no,col]
                rowsumsq = rowsumsq + Cmat[no,col]**2*rd_exc[no,col]
            
            # z1: weighted sum of delayed rates, weights=c*K
            z1ee = cee*Ke*rd_exc[no,no] + c_gl*Ke_gl*rowsum + c_gl*Ke_gl*ext_exc_rate[no,i] # rate from other regions + exc_ext_rate
            z1ei = cei*Ki*rd_inh[no]
            z1ie = cie*Ke*rd_exc[no,no] + c_gl*Ke_gl*ext_inh_rate[no,i] # first test of external rate input to inh. population
            z1ii = cii*Ki*rd_inh[no]
            # z2: weighted sum of delayed rates, weights=c^2*K (see thesis last ch.)
            z2ee = cee**2*Ke*rd_exc[no,no] + c_gl**2*Ke_gl*rowsumsq + c_gl**2*Ke_gl*ext_exc_rate[no,i]
            z2ei = cei**2*Ki*rd_inh[no]
            z2ie = cie**2*Ke*rd_exc[no,no] + c_gl**2*Ke_gl*ext_inh_rate[no,i] # external rate input to inh. population
            z2ii = cii**2*Ki*rd_inh[no]
            
            
            sigmae = np.sqrt( 2*sq_Jee_max*seev[no]*tau_se*taum /      \
                                ((1+z1ee)*taum + tau_se)               \
                             +2*sq_Jei_max*seiv[no]*tau_si*taum /      \
                                ((1+z1ei)*taum + tau_si)  \
                             + sigmae_ext**2 )                  #mV/sqrt(ms)
                             
            sigmai = np.sqrt( 2*sq_Jie_max*siev[no]*tau_se*taum /         \
                                ((1+z1ie)*taum + tau_se)  \
                             +2*sq_Jii_max*siiv[no]*tau_si*taum /         \
                                 ((1+z1ii)*taum + tau_si)    \
                             + sigmai_ext**2)                   #mV/sqrt(ms)
            
            if not filter_sigma:
                sigmae_f = sigmae
                sigmai_f = sigmai
            
    
            # init values for lookup

            tau_exc   = 0 
            Vmean_exc = 0
            tau_inh   = 0   # note: these variables are now scalars!

            # Read the transfer function from the lookup table
            # -------------------------------------------------------------

            # ------- excitatory population

            xid1, yid1, dxid, dyid = fast_interp2_opt(sigmarange, ds, sigmae_f, \
                                                        Irange, dI, mufe[no]-IA[no]/C)
            xid1, yid1 = int(xid1), int(yid1)

            rates_exc[no,i] = interpolate_values(precalc_r, xid1, yid1, dxid, dyid)
            Vmean_exc = interpolate_values(precalc_V, xid1, yid1, dxid, dyid)
            tau_exc = interpolate_values(precalc_tau_mu, xid1, yid1, dxid, dyid)
            tau_sigmae_eff = interpolate_values(precalc_tau_sigma, xid1, yid1, dxid, dyid)

            # ------- inhibitory population

            xid1, yid1, dxid, dyid = fast_interp2_opt(sigmarange, ds, sigmai_f, \
                                                        Irange, dI, mufi[no])
            xid1, yid1 = int(xid1), int(yid1)

            rates_inh[no,i] = interpolate_values(precalc_r, xid1, yid1, dxid, dyid)
            Vmean_inh = interpolate_values(precalc_V, xid1, yid1, dxid, dyid)
            tau_inh = interpolate_values(precalc_tau_mu, xid1, yid1, dxid, dyid)
            tau_sigmai_eff = interpolate_values(precalc_tau_sigma, xid1, yid1, dxid, dyid)


            # -------------------------------------------------------------         
        
            # now everything available for r.h.s:
            
            mufe_rhs = (mue - mufe[no])/tau_exc
            mufi_rhs = (mui - mufi[no])/tau_inh


            IA_rhs = (a*(Vmean_exc-EA) - IA[no] + tauA*b*rates_exc[no,i])/tauA  
            #POSSIBLE ADJUSTMENT: state-depenedent increase
            
            # EQ. 4.43

            if distr_delay:
                rd_exc_rhs = (rates_exc[no,i]-rd_exc[no,no])/tau_de
                rd_inh_rhs = (rates_inh[no,i]-rd_inh[no])/tau_di

            if filter_sigma:
                sigmae_f_rhs = (sigmae - sigmae_f)/tau_sigmae_eff
                sigmai_f_rhs = (sigmai - sigmai_f)/tau_sigmai_eff
            
            # integration of synaptic input (eq. 4.36)
            seem_rhs = ((1-seem[no])*z1ee - seem[no])/tau_se
            seim_rhs = ((1-seim[no])*z1ei - seim[no])/tau_si
            siem_rhs = ((1-siem[no])*z1ie - siem[no])/tau_se
            siim_rhs = ((1-siim[no])*z1ii - siim[no])/tau_si
            seev_rhs = ((1-seem[no])**2 * z2ee  \
                        + (z2ee - 2*tau_se*(z1ee+1))*seev[no])/tau_se**2
            seiv_rhs = ((1-seim[no])**2 * z2ei  \
                        + (z2ei - 2*tau_si*(z1ei+1))*seiv[no])/tau_si**2                        
            siev_rhs = ((1-siem[no])**2 * z2ie  \
                        + (z2ie - 2*tau_se*(z1ie+1))*siev[no])/tau_se**2
            siiv_rhs = ((1-siim[no])**2 * z2ii  \
                        + (z2ii - 2*tau_si*(z1ii+1))*siiv[no])/tau_si**2

            # -------------- integration --------------

            mufe[no] = mufe[no] + dt*mufe_rhs
            mufi[no] = mufi[no] + dt*mufi_rhs

            if distr_delay:
                rd_exc[no,no] = rd_exc[no,no] + dt*rd_exc_rhs
                rd_inh[no] = rd_inh[no] + dt*rd_inh_rhs
            
            if filter_sigma:
                sigmae_f = sigmae_f + dt*sigmae_f_rhs
                sigmai_f = sigmai_f + dt*sigmai_f_rhs
  
            IA[no] = IA[no] + dt*IA_rhs
            seem[no] = seem[no] + dt*seem_rhs
            seim[no] = seim[no] + dt*seim_rhs
            siem[no] = siem[no] + dt*siem_rhs
            siim[no] = siim[no] + dt*siim_rhs
            seev[no] = seev[no] + dt*seev_rhs
            seiv[no] = seiv[no] + dt*seiv_rhs
            siev[no] = siev[no] + dt*siev_rhs
            siiv[no] = siiv[no] + dt*siiv_rhs
               
            # Ensure the variance does not get negative for low activity
            if seev[no] < 0:
                seev[no] = 0.

            if siev[no] < 0:
                siev[no] = 0.

            if seiv[no] < 0:
                seiv[no] = 0.

            if siiv[no] < 0:
                siiv[no] = 0.

            # track inpus (these are only for returning the inputs)
            r_ext_chunk[no,i] = rowsum
            mue_ext_chunk[no, i] = mue_ext[no] + ext_exc_current[no,i]
            mui_ext_chunk[no, i] = mui_ext[no] + ext_inh_current[no,i]

            # formula: mue = Jee_max*seem[no] + Jei_max*seim[no] + mue_ext[no] + ext_exc_current[no,i]
            seem_chunk[no, i] = seem[no]
            siim_chunk[no, i] = siim[no]
            seim_chunk[no, i] = seim[no]
            siem_chunk[no, i] = siem[no]
            seev_chunk[no, i] = seev[no]
            siiv_chunk[no, i] = siiv[no]
            seiv_chunk[no, i] = seiv[no]
            siev_chunk[no, i] = siev[no]             

            mufe_chunk[no, i] = mufe[no]
            mufi_chunk[no, i] = mufi[no]

            sigmae_chunk[no, i] = sigmae_f
            sigmai_chunk[no, i] = sigmai_f

            IA_chunk[no, i] = IA[no]

            tau_exc_chunk[no, i] = tau_exc
            tau_inh_chunk[no, i] = tau_inh
            
            # ornstein-uhlenberg process
            mue_ext[no] = mue_ext[no] + (mue_ext_mean-mue_ext[no])*dt/tau_ou  \
                                      + sigma_ou*sqrt_dt*noise_exc[no]  #mV/ms
            mui_ext[no] = mui_ext[no] + (mui_ext_mean-mui_ext[no])*dt/tau_ou  \
                                      + sigma_ou*sqrt_dt*noise_inh[no]  #mV/ms

            # have to set this zero because of a memory leak in numba 0.43.1
            return_chunks = 0#(mufe_chunk, mufi_chunk, IA_chunk, seem_chunk, siim_chunk, seim_chunk, siem_chunk, seev_chunk, siiv_chunk, seiv_chunk, siev_chunk, mue_ext_chunk, mui_ext_chunk, tau_exc_chunk, tau_inh_chunk, sigmae_chunk, sigmai_chunk)
            return_rhs = 0#(mufe_rhs, mufi_rhs, IA_rhs, seem_rhs, siim_rhs, seim_rhs, siem_rhs, seev_rhs, siiv_rhs, seiv_rhs, siev_rhs, rd_exc_rhs, rd_inh_rhs, sigmae_f_rhs, sigmai_f_rhs)
    
    return rates_exc, rates_inh, t, mufe, mufi, IA, seem, seim, siem, siim, \
                seev, seiv, siev, siiv, \
                return_chunks,\
                return_rhs

@numba.njit(locals = {'idxX': numba.int64, 'idxY':numba.int64})
def interpolate_values(table, xid1, yid1, dxid, dyid):
    output = table[yid1,xid1] *(1-dxid)*(1-dyid) + \
            table[yid1,xid1+1]*dxid*(1-dyid) + \
            table[yid1+1,xid1]*(1-dxid)*dyid + \
            table[yid1+1,xid1+1]*dxid*dyid
    return output


@numba.njit(locals = {'idxX': numba.int64, 'idxY':numba.int64})
def lookup_no_interp(x,dx,xi,y,dy,yi):

    """
    Return the indices for the closest values for a look-up table
    Choose the closest point in the grid

    x     ... range of x values
    xi    ... interpolation value on x-axis
    dx    ... grid width of x ( dx = x[1]-x[0])
               (same for y)
    
    return:   idxX and idxY
    """
 
    if xi > x[0] and xi < x[-1]:
        xid = (xi - x[0])/dx
        xid_floor = np.floor(xid)       
        if xid - xid_floor < dx/2:
            idxX = xid_floor
        else:
            idxX = xid_floor+1
    elif xi < x[0]:
        idxX = 0
    else:
        idxX = len(x)-1

    if yi > y[0] and yi < y[-1]:
        yid = (yi - y[0])/dy
        yid_floor = np.floor(yid)
        if yid - yid_floor < dy/2:
            idxY = yid_floor
        else:
            idxY = yid_floor+1
            
    elif yi < y[0]:
        idxY = 0
    else:
        idxY = len(y)-1

    return idxX,idxY

def adjust_shape(original, target):
    """
    Tiles and then cuts an array (or list or float) such that
    it has the same shape as target at the end.
    This is used to make sure that any input parameter like external current has 
    the same shape as the rate array.
    """

    # make an ext_exc_current ARRAY from a LIST or INT
    if not hasattr(original, "__len__"): 
        original = [original]
    original = np.array(original)

    # repeat original in y until larger (or same size) as target

    # ------- y
    # either (x,) shape or (y,x) shape
    if ( (len(original.shape) == 1) and original.shape[0]>1 ):
        rep_y = target.shape[0]
    elif (target.shape[0] > original.shape[0]): 
        rep_y = int(target.shape[0]/original.shape[0]) + 1
    else: 
        rep_y = 1

    original = np.tile(original,(rep_y,1))

    # ------- x

    if (target.shape[1] > original.shape[1]): rep_x = int(target.shape[1]/original.shape[1]) + 1
    else: rep_x = 1    
    original = np.tile(original,(1,rep_x))

    # cut
    original = original[:target.shape[0], :target.shape[1]]

    return original
  
@numba.njit(locals = {'xid1': numba.int64, 'yid1':numba.int64, 'dxid':numba.float64, 'dyid':numba.float64})    
def fast_interp2_opt(x,dx,xi,y,dy,yi):

    """
    Returns the values needed for interpolation:
    - bilinear (2D) interpolation within ranges, 
    - linear (1D) if "one edge" is crossed, 
    - corner value if "two edges" are crossed

    x     ... range of the x value
    xi    ... interpolation value on x-axis
    dx    ... grid width of x ( dx = x[1]-x[0] )
    (same for y)
    
    return:   xid1    ... index of the lower interpolation value
              dxid    ... distance of xi to the lower interpolation value
              (same for y)
    """
    
    # within all boundaries
    if xi >= x[0] and xi < x[-1] and yi >= y[0] and yi < y[-1]:
        xid = (xi - x[0])/dx
        xid1 = np.floor(xid)
        dxid = xid-xid1       
        yid = (yi - y[0])/dy
        yid1 = np.floor(yid)
        dyid = yid-yid1
        return xid1, yid1, dxid, dyid
    
    # outside one boundary    
    if yi < y[0]:
        yid1 = 0
        dyid = 0.0
        if xi >= x[0] and xi < x[-1]:
            xid = (xi - x[0])/dx
            xid1 = np.floor(xid)
            dxid = xid-xid1
            
        elif xi < x[0]:
            xid1 = 0
            dxid = 0.0
        else: # xi >= x(end)
            xid1 = -1
            dxid = 0.0
        return xid1, yid1, dxid, dyid
        
    if yi >= y[-1]:
        yid1 = -1
        dyid = 0.0
        if xi >= x[0] and xi < x[-1]:
            xid = (xi - x[0])/dx
            xid1 = np.floor(xid)
            dxid = xid-xid1

        elif xi < x[0]:
            xid1 = 0
            dxid = 0.0
        
        else: # xi >= x(end) 
            xid1 = -1
            dxid = 0.0
        return xid1, yid1, dxid, dyid
    
    if xi < x[0]:
        xid1 = 0
        dxid = 0.0
    # We know that yi is within the boundaries
        yid = (yi - y[0])/dy;
        yid1 = np.floor(yid)
        dyid = yid-yid1
        return xid1, yid1, dxid, dyid
     
    if xi >= x[-1]:
        xid1 = -1
        dxid = 0.0
        # We know that yi is within the boundaries
        yid = (yi - y[0])/dy
        yid1 = np.floor(yid)
        dyid = yid-yid1

    return xid1, yid1, dxid, dyid
