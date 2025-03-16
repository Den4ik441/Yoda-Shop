
import React from 'react';
import { Send, MessageSquare, Phone, MapPin } from 'lucide-react';

const Contact = () => {
  return (
    <section id="contact" className="py-20 px-6 md:px-8 gradient-bg">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16 opacity-0 animate-slide-up">
          <h2 className="section-heading">Get In Touch</h2>
          <p className="section-subheading max-w-2xl mx-auto">
            Have questions or need services? Contact us for prompt assistance
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
          <div className="glass-panel p-8 opacity-0 animate-slide-up">
            <h3 className="text-2xl font-medium mb-6">Send a Message</h3>
            
            <form className="space-y-6">
              <div className="space-y-4">
                <input 
                  type="text" 
                  placeholder="Your Name" 
                  className="w-full px-4 py-3 rounded-lg border border-border bg-background/50 focus:outline-none focus:ring-2 focus:ring-primary/30 transition-all"
                />
                <input 
                  type="email" 
                  placeholder="Your Email" 
                  className="w-full px-4 py-3 rounded-lg border border-border bg-background/50 focus:outline-none focus:ring-2 focus:ring-primary/30 transition-all"
                />
                <textarea 
                  placeholder="Your Message" 
                  rows={4}
                  className="w-full px-4 py-3 rounded-lg border border-border bg-background/50 focus:outline-none focus:ring-2 focus:ring-primary/30 transition-all resize-none"
                ></textarea>
              </div>
              
              <button 
                type="submit" 
                className="flex items-center justify-center gap-2 w-full px-6 py-3 bg-primary text-white rounded-lg font-medium hover:bg-primary/90 transition-colors"
              >
                Send Message <Send size={18} />
              </button>
            </form>
          </div>
          
          <div className="space-y-8 opacity-0 animate-slide-up delay-200">
            <div>
              <h3 className="text-2xl font-medium mb-6">Contact Information</h3>
              <p className="text-muted-foreground mb-8">
                Feel free to reach out for any inquiries about our services. We're here to help!
              </p>
              
              <div className="space-y-6">
                {[
                  { 
                    icon: <MessageSquare size={24} className="text-yoda-green" />, 
                    title: "Email",
                    value: "contact@yodashop.com",
                    link: "mailto:contact@yodashop.com"
                  },
                  { 
                    icon: <Phone size={24} className="text-yoda-green" />, 
                    title: "Phone",
                    value: "+1 234 567 890",
                    link: "tel:+1234567890"
                  },
                  { 
                    icon: <MapPin size={24} className="text-yoda-green" />, 
                    title: "Location",
                    value: "Digital Office, Technology Center",
                    link: null
                  },
                ].map((item, index) => (
                  <div 
                    key={index} 
                    className="flex items-start gap-4 opacity-0 animate-fade-in"
                    style={{ animationDelay: `${(index + 3) * 100}ms` }}
                  >
                    <div className="p-3 rounded-xl bg-primary/10 flex-shrink-0">
                      {item.icon}
                    </div>
                    <div>
                      <h4 className="font-medium">{item.title}</h4>
                      {item.link ? (
                        <a 
                          href={item.link} 
                          className="text-muted-foreground hover:text-primary transition-colors"
                        >
                          {item.value}
                        </a>
                      ) : (
                        <p className="text-muted-foreground">{item.value}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            
            <div className="glass-panel p-6 opacity-0 animate-fade-in delay-500">
              <h4 className="font-medium mb-2">Business Hours</h4>
              <p className="text-sm text-muted-foreground">
                Monday - Friday: 9:00 AM - 6:00 PM<br />
                Saturday: 10:00 AM - 4:00 PM<br />
                Sunday: Closed
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default Contact;
